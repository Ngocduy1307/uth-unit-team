package vn.unit.affordability.dossier.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import vn.unit.affordability.dossier.model.Dossier;

import java.util.Optional;

@Repository
public interface DossierRepository extends JpaRepository<Dossier, String> {

    Optional<Dossier> findByApplicationId(String applicationId);

    boolean existsByApplicationId(String applicationId);
}

