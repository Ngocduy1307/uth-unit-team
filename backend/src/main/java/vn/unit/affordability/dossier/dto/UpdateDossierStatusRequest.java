package vn.unit.affordability.dossier.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class UpdateDossierStatusRequest {

    @NotBlank
    private String status;

    @Size(max = 64)
    private String checkerId;

    @Size(max = 500)
    private String reason;
}
