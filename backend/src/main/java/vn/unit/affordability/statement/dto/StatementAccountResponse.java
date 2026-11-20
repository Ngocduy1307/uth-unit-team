package vn.unit.affordability.statement.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class StatementAccountResponse {

    private String id;
    private String dossierId;
    private String bankName;
    private String bankCode;
    private String accountNumber;
    private String accountHolderName;
    private String currency;
    private LocalDate statementFromDate;
    private LocalDate statementToDate;
    private BigDecimal totalCreditAmount;
    private BigDecimal totalDebitAmount;
    private Boolean isHolderMatched;
    private BigDecimal matchConfidence;
    private Boolean isVerified;
    private String verifiedBy;
    private OffsetDateTime verifiedAt;
    private OffsetDateTime createdAt;
}
